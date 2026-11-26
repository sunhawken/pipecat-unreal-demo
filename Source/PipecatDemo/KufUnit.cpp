#include "KufUnit.h"

#include "Components/StaticMeshComponent.h"
#include "DrawDebugHelpers.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"

double AKufUnit::TotalDamage = 0.0;
double AKufUnit::TotalMoved = 0.0;
int32 AKufUnit::TotalKills = 0;

AKufUnit::AKufUnit()
{
	PrimaryActorTick.bCanEverTick = true;
	USceneComponent* Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetRootComponent(Root);
	Body = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Body"));
	Body->SetupAttachment(Root);
	Body->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
	Body->SetCollisionResponseToAllChannels(ECR_Ignore);
	Body->SetCollisionResponseToChannel(ECC_Visibility, ECR_Block);   // so the cursor can pick the unit
	Body->SetCanEverAffectNavigation(false);
}

void AKufUnit::ApplyMesh(UStaticMesh* Mesh)
{
	if (Body && Mesh)
	{
		Body->SetStaticMesh(Mesh);
	}
}

// PLACEHOLDER stats by job family (not decoded from the game yet).
void AKufUnit::InitFromJob()
{
	const FString J = JobName.ToUpper();
	if (!bTeamFromData)
	{
		Team = J.StartsWith(TEXT("H_")) ? 0 : 1;      // fallback only; stage files carry a faction byte
	}
	if (J.Contains(TEXT("ARCHER")) || J.Contains(TEXT("LONGBOW")) || J.Contains(TEXT("PYRO")))
	{
		MaxHealth = 70.0f; AttackRange = 1500.0f; AttackDamage = 8.0f; AttackInterval = 1.2f; Speed = 420.0f;
	}
	else if (J.Contains(TEXT("CATAPULT")) || J.Contains(TEXT("BALLISTA")) || J.Contains(TEXT("MORTAR")) || J.Contains(TEXT("HARPOON")))
	{
		MaxHealth = 90.0f; AttackRange = 3000.0f; AttackDamage = 40.0f; AttackInterval = 3.0f; Speed = 250.0f;
	}
	else if (J.Contains(TEXT("SCORPION")) || J.Contains(TEXT("WYVERN")) || J.Contains(TEXT("GHOUL")) || J.Contains(TEXT("MAMMOTH")) || J.Contains(TEXT("DRAGON")))
	{
		MaxHealth = 320.0f; AttackRange = 260.0f; AttackDamage = 26.0f; AttackInterval = 1.4f; Speed = 520.0f;
	}
	else if (J.Contains(TEXT("CAVALRY")) || J.Contains(TEXT("RIDER")))
	{
		MaxHealth = 140.0f; AttackRange = 220.0f; AttackDamage = 16.0f; AttackInterval = 0.9f; Speed = 800.0f;
	}
	else if (J.Contains(TEXT("WALL")))
	{
		MaxHealth = 400.0f; AttackRange = 1400.0f; AttackDamage = 6.0f; AttackInterval = 1.5f; Speed = 0.0f;   // wall defenders stand still
	}
	else
	{
		MaxHealth = 150.0f; AttackRange = 190.0f; AttackDamage = 14.0f; AttackInterval = 1.0f; Speed = 450.0f;
	}
	Health = MaxHealth;
}

void AKufUnit::BeginPlay()
{
	Super::BeginPlay();
	InitFromJob();
	SnapToGround();
}

void AKufUnit::OrderMove(const FVector& InTarget)
{
	MoveTarget = InTarget;
	bHasMove = true;
	bOrdered = true;
	Target.Reset();
}

void AKufUnit::OrderAttack(AKufUnit* Victim)
{
	Target = Victim;
	bHasMove = false;
	bOrdered = true;
}

AKufUnit* AKufUnit::FindNearestEnemy(float MaxDist) const
{
	AKufUnit* Best = nullptr;
	float BestD = MaxDist * MaxDist;
	for (TActorIterator<AKufUnit> It(GetWorld()); It; ++It)
	{
		AKufUnit* U = *It;
		if (U == this || !U->IsAlive() || U->Team == Team)
		{
			continue;
		}
		const float D = FVector::DistSquared2D(U->GetActorLocation(), GetActorLocation());
		if (D < BestD)
		{
			BestD = D;
			Best = U;
		}
	}
	return Best;
}

void AKufUnit::SnapToGround()
{
	FHitResult Hit;
	FCollisionQueryParams Params(SCENE_QUERY_STAT(KufGround), true, this);
	const FVector P = GetActorLocation();
	if (GetWorld()->LineTraceSingleByChannel(Hit, P + FVector(0, 0, 20000.0f), P - FVector(0, 0, 40000.0f), ECC_Visibility, Params) && !Cast<AKufUnit>(Hit.GetActor()))
	{
		SetActorLocation(FVector(P.X, P.Y, Hit.ImpactPoint.Z));
	}
}

void AKufUnit::Tick(float Dt)
{
	Super::Tick(Dt);
	if (!IsAlive())
	{
		Destroy();
		return;
	}
	Cooldown = FMath::Max(0.0f, Cooldown - Dt);
	ScanTimer -= Dt;

	// Pick a target: enemies always hunt (within aggro range); the player's idle units only react inside attack range.
	if (!Target.IsValid() || !Target->IsAlive())
	{
		Target.Reset();
		if (ScanTimer <= 0.0f)
		{
			ScanTimer = 0.4f;
			const float Reach = (Team == 1) ? AggroRange : AttackRange * 1.2f;
			if (!bHasMove)
			{
				Target = FindNearestEnemy(Reach);
			}
		}
	}

	FVector Goal = GetActorLocation();
	bool bMoving = false;
	if (bHasMove)
	{
		Goal = MoveTarget;
		bMoving = true;
		if (FVector::Dist2D(GetActorLocation(), MoveTarget) < 60.0f)
		{
			bHasMove = false;
			bMoving = false;
		}
	}
	else if (Target.IsValid())
	{
		const float D = FVector::Dist2D(GetActorLocation(), Target->GetActorLocation());
		if (D > AttackRange * 0.9f)
		{
			Goal = Target->GetActorLocation();
			bMoving = true;
		}
		else if (Cooldown <= 0.0f)
		{
			Cooldown = AttackInterval;
			Target->Health -= AttackDamage;
			DamageDealt += AttackDamage;
			TotalDamage += AttackDamage;
			if (!Target->IsAlive())
			{
				Kills++;
				TotalKills++;
			}
			DrawDebugLine(GetWorld(), GetActorLocation() + FVector(0, 0, 150), Target->GetActorLocation() + FVector(0, 0, 150), Team == 0 ? FColor::Cyan : FColor::Red, false, 0.15f, 0, 3.0f);
		}
	}

	if (bMoving && Speed > 0.0f)
	{
		const FVector P = GetActorLocation();
		FVector Dir = (Goal - P);
		Dir.Z = 0.0f;
		const float Len = Dir.Size();
		if (Len > 1.0f)
		{
			Dir /= Len;
			const float Step = FMath::Min(Len, Speed * Dt);
			SetActorLocation(P + Dir * Step);
			SetActorRotation(FRotator(0.0f, Dir.Rotation().Yaw, 0.0f));
			DistanceMoved += Step;
			TotalMoved += Step;
			SnapToGround();
		}
	}

	if (bSelected)
	{
		DrawDebugCircle(GetWorld(), GetActorLocation() + FVector(0, 0, 25), 140.0f, 24, FColor::Green, false, -1.0f, 0, 4.0f, FVector(1, 0, 0), FVector(0, 1, 0), false);
	}
	if (Health < MaxHealth)
	{
		const FVector Top = GetActorLocation() + FVector(0, 0, 260);
		const float Frac = FMath::Clamp(Health / MaxHealth, 0.0f, 1.0f);
		DrawDebugLine(GetWorld(), Top - FVector(0, 80, 0), Top + FVector(0, 80, 0), FColor::Red, false, -1.0f, 0, 6.0f);
		DrawDebugLine(GetWorld(), Top - FVector(0, 80, 0), Top - FVector(0, 80, 0) + FVector(0, 160.0f * Frac, 0), FColor::Green, false, -1.0f, 0, 6.0f);
	}
}
