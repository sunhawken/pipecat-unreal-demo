#include "PipecatPlayerAvatar.h"

#include "PipecatJiggleComponent.h"

#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "GameFramework/Character.h"
#include "GameFramework/Controller.h"
#include "GameFramework/SpringArmComponent.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/Parse.h"

DEFINE_LOG_CATEGORY_STATIC(LogPipecatAvatar, Log, All);

UPipecatPlayerAvatar::UPipecatPlayerAvatar()
{
	PrimaryComponentTick.bCanEverTick = true;
	Mesh = TSoftObjectPtr<USkeletalMesh>(
		FSoftObjectPath(TEXT("/Game/KalinaMannequin/SK_Kalina_Mannequin.SK_Kalina_Mannequin")));
}

void UPipecatPlayerAvatar::BeginPlay()
{
	Super::BeginPlay();

	Character = Cast<ACharacter>(GetOwner());

	// An avatar made with toolsvatarforge is named in Config/PipecatAvatar.txt (one asset path); -PipecatAvatarMesh= overrides
	// it. Otherwise the built-in default is used.
	FString Chosen;
	if (!FParse::Value(FCommandLine::Get(), TEXT("PipecatAvatarMesh="), Chosen) || Chosen.IsEmpty())
	{
		FFileHelper::LoadFileToString(Chosen, *FPaths::Combine(FPaths::ProjectConfigDir(), TEXT("PipecatAvatar.txt")));
	}
	Chosen = Chosen.TrimStartAndEnd().TrimQuotes();
	if (!Chosen.IsEmpty())
	{
		Mesh = TSoftObjectPtr<USkeletalMesh>(FSoftObjectPath(Chosen));
		UE_LOG(LogPipecatAvatar, Log, TEXT("Avatar chosen by AvatarForge / command line: %s"), *Chosen);
	}
	USkeletalMesh* NewMesh = Mesh.LoadSynchronous();
	if (!NewMesh && !Chosen.IsEmpty())
	{
		UE_LOG(LogPipecatAvatar, Warning, TEXT("Could not load %s; falling back to the default avatar"), *Chosen);
		Mesh = TSoftObjectPtr<USkeletalMesh>(FSoftObjectPath(TEXT("/Game/KalinaMannequin/SK_Kalina_Mannequin.SK_Kalina_Mannequin")));
		NewMesh = Mesh.LoadSynchronous();
	}
	if (!Character || !NewMesh)
	{
		UE_LOG(LogPipecatAvatar, Warning, TEXT("No character or no avatar mesh; keeping the default body"));
		SetComponentTickEnabled(false);
		return;
	}

	// Same skeleton as the mannequin, so only the mesh changes: the Animation Blueprint, its animations, the capsule
	// offset and the camera all stay as the template set them.
	Body = Character->GetMesh();
	Body->SetSkeletalMeshAsset(NewMesh);
	UE_LOG(LogPipecatAvatar, Log, TEXT("Avatar %s on %s"), *NewMesh->GetName(), *Character->GetName());

	// Breast and glute secondary motion, driven by her four jiggle bones.
	if (!FParse::Param(FCommandLine::Get(), TEXT("PipecatNoJiggle")))
	{
		UPipecatJiggleComponent* Jiggle = NewObject<UPipecatJiggleComponent>(Character, TEXT("PipecatJiggle"));
		Jiggle->RegisterComponent();
	}

	FParse::Value(FCommandLine::Get(), TEXT("PipecatAvatarPose="), ForcedPose);
	if (ForcedPose.Equals(TEXT("Ref"), ESearchCase::IgnoreCase))
	{
		// No animation at all: the skeleton's reference pose.
		Body->SetAnimationMode(EAnimationMode::AnimationSingleNode);
		Body->SetAnimation(nullptr);
	}

	bPreview = FParse::Param(FCommandLine::Get(), TEXT("PipecatAvatarPreview"));
	if (bPreview)
	{
		if (USpringArmComponent* Boom = Character->FindComponentByClass<USpringArmComponent>())
		{
			float Zoom = 320.0f, Lift = 20.0f;
			FParse::Value(FCommandLine::Get(), TEXT("PipecatAvatarZoom="), Zoom);   // test aid: camera distance (cm)
			FParse::Value(FCommandLine::Get(), TEXT("PipecatAvatarLift="), Lift);   // test aid: camera height offset (cm)
			Boom->TargetArmLength = Zoom;
			Boom->SocketOffset = FVector(0.0f, 0.0f, Lift);
		}
		PreviewYaw = Character->GetActorRotation().Yaw + 180.0f;
	}
	else
	{
		SetComponentTickEnabled(false);
	}
}

void UPipecatPlayerAvatar::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	if (!Character || !bPreview)
	{
		return;
	}

	// Orbit the camera around her.
	PreviewYaw += 30.0f * DeltaTime;
	if (AController* Controller = Character->GetController())
	{
		Controller->SetControlRotation(FRotator(-5.0f, PreviewYaw, 0.0f));
	}
	// Walk / Run: push the character forward so the template's own locomotion animation plays.
	if (ForcedPose.Equals(TEXT("Walk"), ESearchCase::IgnoreCase))
	{
		Character->AddMovementInput(Character->GetActorForwardVector(), 0.3f);
	}
	else if (ForcedPose.Equals(TEXT("Run"), ESearchCase::IgnoreCase))
	{
		Character->AddMovementInput(Character->GetActorForwardVector(), 1.0f);
	}
}
