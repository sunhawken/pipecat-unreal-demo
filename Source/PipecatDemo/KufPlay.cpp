#include "KufPlay.h"

#include "Camera/CameraComponent.h"
#include "Components/InputComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/SpringArmComponent.h"
#include "GameFramework/WorldSettings.h"
#include "InputCoreTypes.h"
#include "KufUnit.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

DEFINE_LOG_CATEGORY_STATIC(LogKufPlay, Log, All);

// ------------------------------------------------------------------------------------------------ pawn
AKufRtsPawn::AKufRtsPawn()
{
	PrimaryActorTick.bCanEverTick = false;
	USceneComponent* Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetRootComponent(Root);
	Boom = CreateDefaultSubobject<USpringArmComponent>(TEXT("Boom"));
	Boom->SetupAttachment(Root);
	Boom->SetRelativeRotation(FRotator(-55.0f, 0.0f, 0.0f));
	Boom->TargetArmLength = 3200.0f;
	Boom->bDoCollisionTest = false;
	Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));
	Camera->SetupAttachment(Boom);
}

// ------------------------------------------------------------------------------------------------ controller
AKufPlayerController::AKufPlayerController()
{
	bShowMouseCursor = true;
	DefaultMouseCursor = EMouseCursor::Crosshairs;
}

void AKufPlayerController::SetupInputComponent()
{
	Super::SetupInputComponent();
	InputComponent->BindKey(EKeys::LeftMouseButton, IE_Pressed, this, &AKufPlayerController::OnSelect);
	InputComponent->BindKey(EKeys::RightMouseButton, IE_Pressed, this, &AKufPlayerController::OnCommand);
	InputComponent->BindKey(EKeys::A, IE_Pressed, this, &AKufPlayerController::OnSelectAll);
	InputComponent->BindKey(EKeys::MouseScrollUp, IE_Pressed, this, &AKufPlayerController::ZoomInKey);
	InputComponent->BindKey(EKeys::MouseScrollDown, IE_Pressed, this, &AKufPlayerController::ZoomOutKey);
}

void AKufPlayerController::ZoomInKey() { Zoom(-250.0f); }
void AKufPlayerController::ZoomOutKey() { Zoom(250.0f); }

void AKufPlayerController::Zoom(float Delta)
{
	if (AKufRtsPawn* P = Cast<AKufRtsPawn>(GetPawn()))
	{
		P->Boom->TargetArmLength = FMath::Clamp(P->Boom->TargetArmLength + Delta, 600.0f, 12000.0f);
	}
}

void AKufPlayerController::PlayerTick(float Dt)
{
	Super::PlayerTick(Dt);
	AKufRtsPawn* P = Cast<AKufRtsPawn>(GetPawn());
	if (!P)
	{
		return;
	}
	FVector Move = FVector::ZeroVector;
	if (IsInputKeyDown(EKeys::W) || IsInputKeyDown(EKeys::Up)) { Move.X += 1.0f; }
	if (IsInputKeyDown(EKeys::S) || IsInputKeyDown(EKeys::Down)) { Move.X -= 1.0f; }
	if (IsInputKeyDown(EKeys::D) || IsInputKeyDown(EKeys::Right)) { Move.Y += 1.0f; }
	if (IsInputKeyDown(EKeys::Left)) { Move.Y -= 1.0f; }
	// edge scrolling
	float MX = 0, MY = 0;
	int32 VX = 0, VY = 0;
	if (GetMousePosition(MX, MY))
	{
		GetViewportSize(VX, VY);
		if (VX > 0 && VY > 0)
		{
			if (MX < 6) { Move.Y -= 1.0f; } else if (MX > VX - 6) { Move.Y += 1.0f; }
			if (MY < 6) { Move.X += 1.0f; } else if (MY > VY - 6) { Move.X -= 1.0f; }
		}
	}
	if (!Move.IsNearlyZero())
	{
		const float Speed = 1.2f * P->Boom->TargetArmLength;
		const FRotator Yaw(0.0f, P->GetActorRotation().Yaw, 0.0f);
		P->AddActorWorldOffset(Yaw.RotateVector(Move.GetSafeNormal()) * Speed * Dt);
	}
	if (GEngine)
	{
		int32 Alive = 0;
		for (const TWeakObjectPtr<AKufUnit>& U : Selected)
		{
			Alive += U.IsValid() && U->IsAlive();
		}
		GEngine->AddOnScreenDebugMessage(8801, 0.0f, FColor::White,
			FString::Printf(TEXT("KUF port (placeholder rules)   selected: %d   LMB select  RMB move/attack  A select all  WASD/edges pan  wheel zoom"), Alive));
	}
}

void AKufPlayerController::ClearSelection()
{
	for (TWeakObjectPtr<AKufUnit>& U : Selected)
	{
		if (U.IsValid())
		{
			U->SetSelected(false);
		}
	}
	Selected.Reset();
}

void AKufPlayerController::OnSelect()
{
	FHitResult Hit;
	GetHitResultUnderCursor(ECC_Visibility, false, Hit);
	AKufUnit* U = Cast<AKufUnit>(Hit.GetActor());
	if (!IsInputKeyDown(EKeys::LeftShift))
	{
		ClearSelection();
	}
	if (U && U->Team == 0 && U->IsAlive())
	{
		U->SetSelected(true);
		Selected.AddUnique(U);
	}
}

void AKufPlayerController::OnSelectAll()
{
	ClearSelection();
	for (TActorIterator<AKufUnit> It(GetWorld()); It; ++It)
	{
		if (It->Team == 0 && It->IsAlive())
		{
			It->SetSelected(true);
			Selected.Add(*It);
		}
	}
}

void AKufPlayerController::OnCommand()
{
	FHitResult Hit;
	if (!GetHitResultUnderCursor(ECC_Visibility, true, Hit))
	{
		return;
	}
	AKufUnit* Enemy = Cast<AKufUnit>(Hit.GetActor());
	int32 Index = 0;
	for (TWeakObjectPtr<AKufUnit>& U : Selected)
	{
		if (!U.IsValid())
		{
			continue;
		}
		if (Enemy && Enemy->Team != U->Team)
		{
			U->OrderAttack(Enemy);
		}
		else
		{
			// spread the group in a loose grid around the clicked point
			const FVector Offset(((Index % 5) - 2) * 160.0f, ((Index / 5) - 1) * 160.0f, 0.0f);
			U->OrderMove(Hit.ImpactPoint + Offset);
			++Index;
		}
	}
}

// ------------------------------------------------------------------------------------------------ game mode
AKufGameMode::AKufGameMode()
{
	DefaultPawnClass = AKufRtsPawn::StaticClass();
	PlayerControllerClass = AKufPlayerController::StaticClass();
	PrimaryActorTick.bCanEverTick = true;
}

void AKufGameMode::BeginPlay()
{
	Super::BeginPlay();
	bSelfTest = FParse::Param(FCommandLine::Get(), TEXT("KufSelfTest"));
	int32 P = 0, E = 0;
	FVector Centre = FVector::ZeroVector;
	for (TActorIterator<AKufUnit> It(GetWorld()); It; ++It)
	{
		if (It->Team == 0)
		{
			++P;
			Centre += It->GetActorLocation();
		}
		else
		{
			++E;
		}
	}
	StartPlayers = P;
	StartEnemies = E;
	UE_LOG(LogKufPlay, Log, TEXT("KUF_PLAY: stage ready, player units %d, enemy units %d (placeholder combat rules; teams from the stage faction byte)"), P, E);
	// put the camera over the player's army
	if (APlayerController* PC = GetWorld()->GetFirstPlayerController())
	{
		if (APawn* Pawn = PC->GetPawn())
		{
			if (P > 0)
			{
				Pawn->SetActorLocation(Centre / P);
			}
		}
	}
}

void AKufGameMode::Tick(float Dt)
{
	Super::Tick(Dt);
	if (bSelfTest)
	{
		RunSelfTestStep(Dt);
	}
}

// Headless check used as evidence: units must be spawned, must move when ordered and must fight (damage dealt).
void AKufGameMode::RunSelfTestStep(float Dt)
{
	SelfTestTime += Dt;
	if (!bSelfTestOrdered && SelfTestTime > 2.0f)
	{
		bSelfTestOrdered = true;
		GetWorld()->GetWorldSettings()->SetTimeDilation(6.0f);
		int32 Ordered = 0;
		for (TActorIterator<AKufUnit> It(GetWorld()); It; ++It)
		{
			if (It->Team != 0)
			{
				continue;
			}
			AKufUnit* Best = nullptr;
			float BestD = TNumericLimits<float>::Max();
			for (TActorIterator<AKufUnit> It2(GetWorld()); It2; ++It2)
			{
				if (It2->Team == 1 && It2->IsAlive())
				{
					const float D = FVector::DistSquared2D(It2->GetActorLocation(), It->GetActorLocation());
					if (D < BestD) { BestD = D; Best = *It2; }
				}
			}
			if (Best)
			{
				It->OrderAttack(Best);
				++Ordered;
			}
		}
		UE_LOG(LogKufPlay, Log, TEXT("KUF_SELFTEST: attack orders issued to %d player units"), Ordered);
	}
	if (SelfTestTime > 75.0f)
	{
		int32 P = 0, E = 0;
		for (TActorIterator<AKufUnit> It(GetWorld()); It; ++It)
		{
			(It->Team == 0 ? P : E)++;
		}
		const bool bOk = StartPlayers > 0 && StartEnemies > 0 && AKufUnit::TotalMoved > 500.0 && AKufUnit::TotalDamage > 0.0;
		UE_LOG(LogKufPlay, Log, TEXT("KUF_SELFTEST: start players=%d enemies=%d | end players=%d enemies=%d | moved=%.0f cm damage=%.0f kills=%d | RESULT=%s"),
			StartPlayers, StartEnemies, P, E, AKufUnit::TotalMoved, AKufUnit::TotalDamage, AKufUnit::TotalKills, bOk ? TEXT("OK") : TEXT("FAIL"));
		FPlatformMisc::RequestExit(false);
	}
}
